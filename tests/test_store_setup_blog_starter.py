"""Tests for ``engines.store_setup.blog_starter``.

Generator produces 3 niche-aware article specs per launch;
applier auto-creates a ``News`` blog (if no blog_id supplied)
via ``SHOPIFY_CREATE_BLOG``, then pushes each article via
``SHOPIFY_CREATE_ARTICLE``. Records via Pattern Z.

Coverage:
  1. Generator: empty store_name -> empty dict.
  2. Generator: 3 articles per niche.
  3. Generator: every shipped niche has full article shape.
  4. Generator: author_name threaded when supplied.
  5. Generator: unknown niche falls back to general.
  6. Applier: no spec / non-dict / empty articles.
  7. Applier: router_unavailable.
  8. Applier: pre-supplied blog_id used directly (no
     create_blog call).
  9. Applier: no blog_id triggers auto-create.
 10. Applier: auto-create fails -> all articles fail with
     blog_unavailable.
 11. Applier: per-article success path + Pattern Z.
 12. Applier: per-article partial failure isolation.
 13. Applier: adapter raise for one article doesn't block
     others.
 14. store_id propagation.
 15. Article params: blog_id + title + body_html + tags + summary
     + is_published forwarded correctly.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from engines.store_setup.blog_starter import (
    _NICHE_ARTICLES,
    apply_blog_starter,
    generate_blog_starter,
)


def _ok(data=None):
    return SimpleNamespace(
        ok=True, data=data or {}, error=None,
    )


def _fail(err: str):
    return SimpleNamespace(ok=False, data=None, error=err)


# ── Generator ─────────────────────────────────────────────────


class TestGeneratorEmpty:

    def test_empty_store_name(self):
        assert generate_blog_starter(store_name="") == {}
        assert generate_blog_starter(store_name="   ") == {}
        assert generate_blog_starter(store_name=None) == {}


class TestGeneratorShape:

    def test_three_articles_per_niche(self):
        for niche in _NICHE_ARTICLES:
            spec = generate_blog_starter(
                store_name="Acme", niche=niche,
            )
            assert len(spec["articles"]) == 3, niche

    def test_every_article_has_full_shape(self):
        for niche in _NICHE_ARTICLES:
            spec = generate_blog_starter(
                store_name="Acme", niche=niche,
            )
            for article in spec["articles"]:
                assert article["title"], niche
                assert article["summary"], niche
                assert (
                    article["body_html"].startswith("<h2>")
                ), niche
                # Substantive content -- not a placeholder
                assert len(article["body_html"]) >= 500, (
                    niche, article["title"],
                )
                assert isinstance(article["tags"], list)
                assert len(article["tags"]) >= 3

    def test_author_name_threaded(self):
        spec = generate_blog_starter(
            store_name="Acme", author_name="Jane Doe",
        )
        for article in spec["articles"]:
            assert article["author_name"] == "Jane Doe"

    def test_no_author_no_field(self):
        spec = generate_blog_starter(store_name="Acme")
        for article in spec["articles"]:
            assert "author_name" not in article

    def test_unknown_niche_falls_back_to_general(self):
        spec = generate_blog_starter(
            store_name="Acme", niche="ufo_parts",
        )
        # Falls back to general's 3 articles
        general_titles = {
            t for t, _, _, _ in _NICHE_ARTICLES["general"]
        }
        out_titles = {a["title"] for a in spec["articles"]}
        assert out_titles == general_titles


# ── Applier: edge cases ──────────────────────────────────────


class TestApplierEmpty:

    def test_non_dict(self):
        out = apply_blog_starter(None)  # type: ignore[arg-type]
        assert out["applied_count"] == 0

    def test_empty_spec(self):
        out = apply_blog_starter({})
        assert out["applied_count"] == 0

    def test_spec_without_articles(self):
        out = apply_blog_starter({"store_name": "Acme"})
        assert out["applied_count"] == 0


class TestApplierRouterFailure:

    def test_router_unavailable_records_each_article(self):
        spec = generate_blog_starter(
            store_name="Acme", niche="beauty",
        )
        with patch(
            "engines.store_setup.blog_starter._get_router",
            return_value=None,
        ), patch(
            "engines.store_setup.blog_starter."
            "record_writeback",
        ) as record_mock:
            out = apply_blog_starter(spec)
        assert out["applied_count"] == 0
        # 3 articles -> 3 results -> 3 failure records
        assert len(out["results"]) == 3
        assert all(
            r["error"] == "router_unavailable"
            for r in out["results"]
        )
        assert record_mock.call_count == 3


# ── Applier: blog resolution ──────────────────────────────────


class TestBlogResolution:

    def test_supplied_blog_id_skips_create_blog(self):
        """Pre-supplied blog_id means we never call
        SHOPIFY_CREATE_BLOG -- no wasted writes."""
        router = MagicMock()

        def _exec(cap, params):
            cap_name = getattr(cap, "value", "")
            assert cap_name != "shopify_create_blog", (
                "create_blog should NOT be called when "
                "blog_id is supplied"
            )
            return _ok({"article": {"id": "gid://a/1"}})

        router.execute.side_effect = _exec
        spec = generate_blog_starter(
            store_name="Acme", niche="beauty",
        )
        with patch(
            "engines.store_setup.blog_starter._get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.blog_starter."
            "record_writeback",
        ):
            out = apply_blog_starter(
                spec, blog_id="gid://shopify/Blog/1",
            )
        assert out["applied_count"] == 3
        assert out["blog_id"] == "gid://shopify/Blog/1"

    def test_no_blog_id_auto_creates(self):
        router = MagicMock()
        create_blog_calls: list[Any] = []

        def _exec(cap, params):
            cap_name = getattr(cap, "value", "")
            if cap_name == "shopify_create_blog":
                create_blog_calls.append(params)
                return _ok({"blog": {
                    "id": "gid://shopify/Blog/99",
                    "title": "News",
                }})
            return _ok({"article": {"id": "gid://a/1"}})

        router.execute.side_effect = _exec
        spec = generate_blog_starter(
            store_name="Acme", niche="beauty",
        )
        with patch(
            "engines.store_setup.blog_starter._get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.blog_starter."
            "record_writeback",
        ):
            out = apply_blog_starter(spec)
        # create_blog called once with default title
        assert len(create_blog_calls) == 1
        assert create_blog_calls[0]["title"] == "News"
        assert out["blog_id"] == "gid://shopify/Blog/99"
        assert out["blog_title"] == "News"
        assert out["applied_count"] == 3

    def test_custom_blog_title_used(self):
        router = MagicMock()
        captured_titles: list[str] = []

        def _exec(cap, params):
            cap_name = getattr(cap, "value", "")
            if cap_name == "shopify_create_blog":
                captured_titles.append(params["title"])
                return _ok({"blog": {
                    "id": "gid://shopify/Blog/99",
                    "title": params["title"],
                }})
            return _ok({"article": {"id": "gid://a/1"}})

        router.execute.side_effect = _exec
        spec = generate_blog_starter(store_name="Acme")
        with patch(
            "engines.store_setup.blog_starter._get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.blog_starter."
            "record_writeback",
        ):
            out = apply_blog_starter(
                spec, blog_title="Field Notes",
            )
        assert captured_titles == ["Field Notes"]
        assert out["blog_title"] == "Field Notes"

    def test_blog_create_failure_blocks_articles(self):
        router = MagicMock()

        def _exec(cap, params):
            cap_name = getattr(cap, "value", "")
            if cap_name == "shopify_create_blog":
                return _fail("title taken")
            raise AssertionError(
                "article create should not be called "
                "when blog create failed"
            )

        router.execute.side_effect = _exec
        spec = generate_blog_starter(store_name="Acme")
        with patch(
            "engines.store_setup.blog_starter._get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.blog_starter."
            "record_writeback",
        ) as record_mock:
            out = apply_blog_starter(spec)
        assert out["applied_count"] == 0
        assert all(
            r["error"] == "blog_unavailable"
            for r in out["results"]
        )
        # Per-article failure recorded
        assert record_mock.call_count == 3


# ── Applier: per-article ─────────────────────────────────────


class TestApplierArticles:

    def test_articles_forwarded_with_full_params(self):
        router = MagicMock()
        captured_params: list[dict[str, Any]] = []

        def _exec(cap, params):
            cap_name = getattr(cap, "value", "")
            if cap_name == "shopify_create_blog":
                return _ok({"blog": {
                    "id": "gid://shopify/Blog/1",
                    "title": "News",
                }})
            captured_params.append(params)
            return _ok({"article": {"id": "gid://a/1"}})

        router.execute.side_effect = _exec
        spec = generate_blog_starter(
            store_name="Acme", niche="beauty",
        )
        with patch(
            "engines.store_setup.blog_starter._get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.blog_starter."
            "record_writeback",
        ):
            apply_blog_starter(spec)
        assert len(captured_params) == 3
        for params, article in zip(
            captured_params, spec["articles"],
        ):
            assert (
                params["blog_id"] == "gid://shopify/Blog/1"
            )
            assert params["title"] == article["title"]
            assert params["body_html"] == article["body_html"]
            assert params["summary"] == article["summary"]
            assert params["tags"] == article["tags"]
            assert params["is_published"] is True

    def test_partial_failure_per_article(self):
        """One article rejection doesn't kill the others."""
        router = MagicMock()

        def _exec(cap, params):
            cap_name = getattr(cap, "value", "")
            if cap_name == "shopify_create_blog":
                return _ok({"blog": {
                    "id": "gid://shopify/Blog/1",
                    "title": "News",
                }})
            if (
                params.get("title")
                == _NICHE_ARTICLES["beauty"][1][0]
            ):
                return _fail("duplicate handle")
            return _ok({"article": {"id": "gid://a/1"}})

        router.execute.side_effect = _exec
        spec = generate_blog_starter(
            store_name="Acme", niche="beauty",
        )
        with patch(
            "engines.store_setup.blog_starter._get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.blog_starter."
            "record_writeback",
        ):
            out = apply_blog_starter(spec)
        # 2 of 3 succeeded
        assert out["applied_count"] == 2
        oks = [r["ok"] for r in out["results"]]
        # second article is the failing one
        assert oks == [True, False, True]
        # The failing one's error is propagated
        assert (
            "duplicate handle" in out["results"][1]["error"]
        )

    def test_article_raise_isolates(self):
        router = MagicMock()
        call_count = {"i": 0}

        def _exec(cap, params):
            cap_name = getattr(cap, "value", "")
            if cap_name == "shopify_create_blog":
                return _ok({"blog": {
                    "id": "gid://shopify/Blog/1",
                    "title": "News",
                }})
            call_count["i"] += 1
            if call_count["i"] == 2:
                raise RuntimeError("network")
            return _ok({"article": {"id": "gid://a/1"}})

        router.execute.side_effect = _exec
        spec = generate_blog_starter(
            store_name="Acme", niche="beauty",
        )
        with patch(
            "engines.store_setup.blog_starter._get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.blog_starter."
            "record_writeback",
        ):
            out = apply_blog_starter(spec)
        # 2 of 3 succeeded; the raising one captured the
        # exception as adapter_raise
        assert out["applied_count"] == 2
        assert (
            "network" in (out["results"][1]["error"] or "")
        )

    def test_article_id_captured_on_success(self):
        router = MagicMock()
        ids = iter([
            "gid://a/1", "gid://a/2", "gid://a/3",
        ])

        def _exec(cap, params):
            cap_name = getattr(cap, "value", "")
            if cap_name == "shopify_create_blog":
                return _ok({"blog": {
                    "id": "gid://shopify/Blog/1",
                    "title": "News",
                }})
            return _ok({"article": {"id": next(ids)}})

        router.execute.side_effect = _exec
        spec = generate_blog_starter(
            store_name="Acme", niche="beauty",
        )
        with patch(
            "engines.store_setup.blog_starter._get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.blog_starter."
            "record_writeback",
        ):
            out = apply_blog_starter(spec)
        captured_ids = [
            r["article_id"] for r in out["results"]
        ]
        assert captured_ids == [
            "gid://a/1", "gid://a/2", "gid://a/3",
        ]


# ── store_id propagation ──────────────────────────────────────


class TestStoreIdPropagation:

    def test_store_id_recorded_per_article(self):
        router = MagicMock()

        def _exec(cap, params):
            cap_name = getattr(cap, "value", "")
            if cap_name == "shopify_create_blog":
                return _ok({"blog": {
                    "id": "gid://shopify/Blog/1",
                    "title": "News",
                }})
            return _ok({"article": {"id": "gid://a/1"}})

        router.execute.side_effect = _exec
        spec = generate_blog_starter(
            store_name="Acme", niche="beauty",
        )
        with patch(
            "engines.store_setup.blog_starter._get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.blog_starter."
            "record_writeback",
        ) as record_mock:
            apply_blog_starter(spec, store_id="store-a")
        assert record_mock.call_count == 3
        for call in record_mock.call_args_list:
            assert (
                call.kwargs["params"]["store_id"]
                == "store-a"
            )
