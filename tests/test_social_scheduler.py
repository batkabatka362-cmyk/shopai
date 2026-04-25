"""SocialScheduler regression — queue + publish behaviour."""
from __future__ import annotations

import os
import tempfile
import time
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock

import pytest

from engines.social_scheduler import SocialScheduler


@pytest.fixture
def scheduler():
    tmp = tempfile.NamedTemporaryFile(
        suffix=".db", delete=False,
    )
    tmp.close()
    s = SocialScheduler.open(tmp.name)
    yield s
    s.close()
    os.unlink(tmp.name)


@dataclass
class _FakeResult:
    ok: bool = True
    error: Any = None
    data: dict[str, Any] = field(default_factory=dict)


def _router(outcomes: dict[str, list[_FakeResult]]):
    """Fake router. ``outcomes`` keyed by adapter name;
    each list popped left-to-right across calls."""
    calls: list[dict] = []

    def execute(capability, params, *, adapter=None):
        calls.append({
            "capability": capability.value,
            "adapter": adapter,
            "params": params,
        })
        key = adapter or "default"
        if key in outcomes and outcomes[key]:
            return outcomes[key].pop(0)
        return _FakeResult(ok=False, error="no-config")

    r = MagicMock()
    r.execute.side_effect = execute
    r._calls = calls
    return r


# ── Enqueue ────────────────────────────────────────────────


class TestEnqueue:
    def test_enqueue_happy(self, scheduler):
        post_id = scheduler.enqueue(
            platforms=["instagram"],
            text="cozy lamp",
            image_url="https://cdn/x.jpg",
        )
        assert post_id.startswith("sp_")
        post = scheduler.get(post_id)
        assert post is not None
        assert post.text == "cozy lamp"
        assert post.state == "queued"
        assert post.platforms == ("instagram",)

    def test_empty_platforms_rejected(self, scheduler):
        with pytest.raises(ValueError):
            scheduler.enqueue(
                platforms=[], text="hi",
            )

    def test_unknown_platform_rejected(self, scheduler):
        with pytest.raises(ValueError):
            scheduler.enqueue(
                platforms=["myspace"], text="hi",
            )

    def test_no_content_rejected(self, scheduler):
        with pytest.raises(ValueError):
            scheduler.enqueue(
                platforms=["instagram"], text="",
            )

    def test_idempotent_on_trace_id(self, scheduler):
        first = scheduler.enqueue(
            platforms=["instagram"],
            text="x",
            image_url="https://y/z.jpg",
            trace_id="winner-P-1",
        )
        second = scheduler.enqueue(
            platforms=["instagram"],
            text="different now",
            image_url="https://y/z.jpg",
            trace_id="winner-P-1",
        )
        assert first == second
        # Only one row exists in the queue.
        rows = scheduler.list_all()
        assert len(rows) == 1

    def test_idempotency_doesnt_block_after_publish(
        self, scheduler,
    ):
        """Once a trace has been published, the next enqueue
        with the same trace_id creates a new row (we want to
        be able to post about the same product multiple
        times)."""
        first_id = scheduler.enqueue(
            platforms=["instagram"],
            text="hi", image_url="https://y/1.jpg",
            trace_id="same-trace",
        )
        # Simulate publish by updating state directly.
        scheduler._conn.execute(
            "UPDATE social_queue SET state='published' "
            "WHERE post_id = ?",
            (first_id,),
        )
        scheduler._conn.commit()
        second_id = scheduler.enqueue(
            platforms=["instagram"],
            text="hi again", image_url="https://y/2.jpg",
            trace_id="same-trace",
        )
        assert first_id != second_id

    def test_hashtags_stored(self, scheduler):
        post_id = scheduler.enqueue(
            platforms=["instagram"],
            text="cozy",
            image_url="https://y/x.jpg",
            hashtags=["cozy", "wellness", ""],
        )
        post = scheduler.get(post_id)
        assert "cozy" in post.hashtags
        assert "wellness" in post.hashtags


# ── Due / listing ─────────────────────────────────────────


class TestListing:
    def test_list_due_honours_time(self, scheduler):
        past = int(time.time()) - 10
        future = int(time.time()) + 3600
        scheduler.enqueue(
            platforms=["instagram"], text="past",
            image_url="https://y/p.jpg",
            publish_at_unix=past,
        )
        scheduler.enqueue(
            platforms=["instagram"], text="future",
            image_url="https://y/f.jpg",
            publish_at_unix=future,
        )
        due = scheduler.list_due()
        assert len(due) == 1
        assert due[0].text == "past"

    def test_list_all_returns_all_states(self, scheduler):
        scheduler.enqueue(
            platforms=["instagram"], text="a",
            image_url="https://y.jpg",
        )
        scheduler.enqueue(
            platforms=["instagram"], text="b",
            image_url="https://z.jpg",
        )
        assert len(scheduler.list_all()) == 2


# ── process_due ───────────────────────────────────────────


class TestProcessDue:
    def test_no_router_returns_summary(self, scheduler):
        scheduler.enqueue(
            platforms=["instagram"], text="hi",
            image_url="https://y.jpg",
        )
        out = scheduler.process_due(router=None)
        assert out["published"] == 0
        assert "reason" in out

    def test_happy_path_publishes(self, scheduler):
        post_id = scheduler.enqueue(
            platforms=["instagram"],
            text="hi",
            image_url="https://y.jpg",
            publish_at_unix=int(time.time()) - 10,
        )
        router = _router({
            "instagram": [_FakeResult(
                ok=True, data={"post_id": "IG-99"},
            )],
        })
        out = scheduler.process_due(router=router)
        assert out["published"] == 1
        assert out["failed"] == 0
        # Row transitioned to published.
        post = scheduler.get(post_id)
        assert post.state == "published"
        # Attempts counter bumped.
        assert post.attempts == 1

    def test_multi_platform_all_must_succeed(self, scheduler):
        post_id = scheduler.enqueue(
            platforms=["instagram", "facebook_page"],
            text="cozy",
            image_url="https://y.jpg",
            publish_at_unix=int(time.time()) - 10,
        )
        # IG ok, FB fails → overall failure.
        router = _router({
            "instagram": [_FakeResult(
                ok=True, data={"post_id": "IG"},
            )],
            "facebook_page": [_FakeResult(
                ok=False, error="rate limit",
            )],
        })
        out = scheduler.process_due(router=router)
        assert out["failed"] == 1
        post = scheduler.get(post_id)
        # Still retriable — state back to queued.
        assert post.state == "queued"
        assert post.attempts == 1
        assert "rate limit" in post.last_error

    def test_retries_exhausted_marks_failed(self, scheduler):
        post_id = scheduler.enqueue(
            platforms=["instagram"],
            text="hi", image_url="https://y.jpg",
            publish_at_unix=int(time.time()) - 10,
        )
        # 3 consecutive failures → state = failed.
        router = _router({
            "instagram": [
                _FakeResult(ok=False, error="err-1"),
                _FakeResult(ok=False, error="err-2"),
                _FakeResult(ok=False, error="err-3"),
            ],
        })
        for _ in range(3):
            scheduler.process_due(router=router)
        post = scheduler.get(post_id)
        assert post.state == "failed"
        assert post.attempts == 3

    def test_future_posts_not_published(self, scheduler):
        scheduler.enqueue(
            platforms=["instagram"],
            text="later",
            image_url="https://y.jpg",
            publish_at_unix=int(time.time()) + 3600,
        )
        router = _router({
            "instagram": [_FakeResult(
                ok=True, data={"post_id": "x"},
            )],
        })
        out = scheduler.process_due(router=router)
        assert out["published"] == 0
        assert out["processed"] == 0

    def test_exception_in_publish_recorded_as_failure(
        self, scheduler,
    ):
        post_id = scheduler.enqueue(
            platforms=["instagram"],
            text="hi", image_url="https://y.jpg",
            publish_at_unix=int(time.time()) - 10,
        )
        router = MagicMock()
        router.execute.side_effect = RuntimeError("kaboom")
        out = scheduler.process_due(router=router)
        assert out["failed"] == 1
        post = scheduler.get(post_id)
        assert "RuntimeError" in post.last_error

    def test_router_receives_adapter_pin(self, scheduler):
        """The scheduler should ask the router for a SPECIFIC
        adapter per platform so IG posts don't get rerouted
        to FB when both are configured."""
        scheduler.enqueue(
            platforms=["instagram"],
            text="hi", image_url="https://y.jpg",
            publish_at_unix=int(time.time()) - 10,
        )
        router = _router({
            "instagram": [_FakeResult(
                ok=True, data={"post_id": "IG-1"},
            )],
        })
        scheduler.process_due(router=router)
        # Call record shows adapter='instagram' was passed.
        call = router._calls[0]
        assert call["adapter"] == "instagram"


# ── Persistence ──────────────────────────────────────────


class TestPersistence:
    def test_reopen_preserves_queue(self, tmp_path):
        db = str(tmp_path / "soc.db")
        s1 = SocialScheduler.open(db)
        s1.enqueue(
            platforms=["instagram"],
            text="persisted",
            image_url="https://y.jpg",
        )
        s1.close()

        s2 = SocialScheduler.open(db)
        all_rows = s2.list_all()
        assert len(all_rows) == 1
        assert all_rows[0].text == "persisted"
        s2.close()
