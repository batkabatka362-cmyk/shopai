"""SocialScheduler — SQLite-backed queue + publisher.

Contract:

  * ``enqueue(...)`` — writes a queued row. Idempotent on
    ``trace_id`` when supplied: a duplicate enqueue with the
    same trace_id on a non-published post is a no-op
    (§4b.D). Returns the post_id (string) of the queued row.
  * ``process_due(router, now=None)`` — pulls rows whose
    ``publish_at_unix`` ≤ now AND whose state is ``queued``,
    dispatches each to the configured platforms, and
    transitions the row to ``published`` or ``failed``.
    Returns a summary dict the caller can log / record
    as a cycle outcome.
  * ``list_due(now=None)`` / ``list_all(limit=N)`` —
    observability.

State machine:

    queued ──(publish ok)──> published
     ├────(publish fail retries exhausted)──> failed
     └────(publish fail, retries remain)──> queued  (next cycle)

Retries: 3 attempts per platform per post. The platform's
last error is surfaced in the row's ``last_error`` column so
owner can trace what went wrong without trawling logs.

The scheduler does not fabricate content — it only delivers
what engines hand it. Brand gate (§ core/brand/pre_ship)
should run at enqueue time; this scheduler assumes inbound
text + media are already vetted.
"""
from __future__ import annotations

import dataclasses
import json
import logging
import os
import sqlite3
import threading
import time
import uuid
from typing import Any, Iterable


_logger = logging.getLogger("shopai.social_scheduler")

_DEFAULT_DB_PATH = os.path.join("data", "social_scheduler.db")
_MAX_ATTEMPTS = 3

# Which platforms the scheduler knows how to publish to.
# Map platform name → adapter name in the registry.
_PLATFORM_ADAPTERS = {
    "instagram": "instagram",
    "facebook_page": "facebook_page",
}


@dataclasses.dataclass(frozen=True)
class SocialPost:
    """One row in the queue."""
    post_id: str
    platforms: tuple[str, ...]
    text: str
    image_url: str
    video_url: str
    link_url: str
    hashtags: tuple[str, ...]
    publish_at_unix: int
    trace_id: str
    state: str                 # queued | published | failed
    attempts: int
    last_error: str
    created_at_unix: int

    def as_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


def _connect(db_path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS social_queue (
            post_id         TEXT PRIMARY KEY,
            platforms       TEXT NOT NULL,
            text            TEXT NOT NULL DEFAULT '',
            image_url       TEXT NOT NULL DEFAULT '',
            video_url       TEXT NOT NULL DEFAULT '',
            link_url        TEXT NOT NULL DEFAULT '',
            hashtags        TEXT NOT NULL DEFAULT '[]',
            publish_at_unix INTEGER NOT NULL,
            trace_id        TEXT NOT NULL DEFAULT '',
            state           TEXT NOT NULL DEFAULT 'queued',
            attempts        INTEGER NOT NULL DEFAULT 0,
            last_error      TEXT NOT NULL DEFAULT '',
            created_at_unix INTEGER NOT NULL,
            published_post_ids TEXT NOT NULL DEFAULT '{}'
        )
        """,
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_social_due "
        "ON social_queue(state, publish_at_unix)",
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_social_trace "
        "ON social_queue(trace_id)",
    )
    conn.commit()
    return conn


class SocialScheduler:
    """Instance holds an open connection + a lock for writes."""

    def __init__(self, db_path: str = _DEFAULT_DB_PATH) -> None:
        self._path = db_path
        self._conn = _connect(db_path)
        self._lock = threading.Lock()

    # ── Construction helpers ──────────────────────────

    @classmethod
    def open(
        cls, db_path: str | None = None,
    ) -> "SocialScheduler":
        return cls(db_path or _DEFAULT_DB_PATH)

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except Exception:  # noqa: BLE001
                pass

    # ── Enqueue ──────────────────────────────────────

    def enqueue(
        self,
        *,
        platforms: Iterable[str],
        text: str = "",
        image_url: str = "",
        video_url: str = "",
        link_url: str = "",
        hashtags: Iterable[str] | None = None,
        publish_at_unix: int | None = None,
        trace_id: str = "",
    ) -> str:
        """Add a post. Returns the post_id. Idempotent on
        non-empty ``trace_id`` — a second call with the same
        trace while the first is still ``queued`` returns
        the existing post_id.
        """
        platform_list = tuple(
            p for p in (platforms or ())
            if isinstance(p, str) and p
        )
        if not platform_list:
            raise ValueError(
                "platforms: at least one required",
            )
        for p in platform_list:
            if p not in _PLATFORM_ADAPTERS:
                raise ValueError(
                    f"unknown platform {p!r}; "
                    f"supported: {sorted(_PLATFORM_ADAPTERS)}",
                )
        if not text and not image_url and not video_url:
            raise ValueError(
                "one of text / image_url / video_url required",
            )
        if publish_at_unix is None:
            publish_at_unix = int(time.time())
        try:
            publish_at_unix = int(publish_at_unix)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "publish_at_unix must be int",
            ) from exc

        tags_list = [
            str(t).strip() for t in (hashtags or ()) if t
        ]

        with self._lock:
            if trace_id:
                row = self._conn.execute(
                    "SELECT post_id, state FROM social_queue "
                    "WHERE trace_id = ? ORDER BY created_at_unix "
                    "DESC LIMIT 1",
                    (trace_id,),
                ).fetchone()
                if row and row["state"] == "queued":
                    return str(row["post_id"])

            post_id = f"sp_{uuid.uuid4().hex[:16]}"
            self._conn.execute(
                "INSERT INTO social_queue ("
                "post_id, platforms, text, image_url, "
                "video_url, link_url, hashtags, "
                "publish_at_unix, trace_id, state, "
                "attempts, last_error, created_at_unix) "
                "VALUES (?,?,?,?,?,?,?,?,?,'queued',0,'',?)",
                (
                    post_id,
                    json.dumps(list(platform_list)),
                    str(text),
                    str(image_url),
                    str(video_url),
                    str(link_url),
                    json.dumps(tags_list),
                    int(publish_at_unix),
                    str(trace_id),
                    int(time.time()),
                ),
            )
            self._conn.commit()
            return post_id

    # ── Inspection ───────────────────────────────────

    def list_due(
        self,
        *,
        now: int | None = None,
        limit: int = 50,
    ) -> list[SocialPost]:
        now = int(now if now is not None else time.time())
        rows = self._conn.execute(
            "SELECT * FROM social_queue "
            "WHERE state = 'queued' AND publish_at_unix <= ? "
            "ORDER BY publish_at_unix ASC LIMIT ?",
            (now, max(1, min(int(limit), 500))),
        ).fetchall()
        return [_row_to_post(r) for r in rows]

    def list_all(self, *, limit: int = 100) -> list[SocialPost]:
        rows = self._conn.execute(
            "SELECT * FROM social_queue "
            "ORDER BY created_at_unix DESC LIMIT ?",
            (max(1, min(int(limit), 1000)),),
        ).fetchall()
        return [_row_to_post(r) for r in rows]

    def get(self, post_id: str) -> SocialPost | None:
        row = self._conn.execute(
            "SELECT * FROM social_queue WHERE post_id = ?",
            (post_id,),
        ).fetchone()
        return _row_to_post(row) if row else None

    # ── Processing ───────────────────────────────────

    def process_due(
        self,
        *,
        router: Any,
        now: int | None = None,
        max_posts: int = 20,
    ) -> dict[str, Any]:
        """Publish all queued posts whose publish_at has
        passed. Per-post errors don't stop the loop — the
        summary captures counts so the autopilot cycle can
        observe + surface them.
        """
        if router is None:
            return {
                "published": 0, "failed": 0, "skipped": 0,
                "reason": "no router provided",
            }
        due = self.list_due(now=now, limit=max_posts)
        published = 0
        failed = 0
        skipped = 0
        for post in due:
            try:
                outcome = self._publish_one(post, router=router)
            except Exception as exc:  # noqa: BLE001
                _logger.warning(
                    "social_scheduler: %s raised %s: %s",
                    post.post_id,
                    type(exc).__name__, exc,
                )
                failed += 1
                self._record_failure(
                    post,
                    last_error=(
                        f"{type(exc).__name__}: {exc}"
                    )[:400],
                )
                continue
            if outcome["state"] == "published":
                published += 1
            elif outcome["state"] == "failed":
                failed += 1
            else:
                skipped += 1
        return {
            "published": published,
            "failed": failed,
            "skipped": skipped,
            "processed": published + failed + skipped,
        }

    def _publish_one(
        self,
        post: SocialPost,
        *,
        router: Any,
    ) -> dict[str, Any]:
        from core.adapters import Capability
        per_platform: dict[str, Any] = {}
        all_ok = True
        for plat in post.platforms:
            params = {
                "text": post.text,
                "image_url": post.image_url,
                "video_url": post.video_url,
                "link_url": post.link_url,
                "hashtags": list(post.hashtags),
                "trace_id": post.trace_id,
            }
            # Pin to the specific adapter name so the router
            # doesn't reroute Instagram posts to Facebook
            # when both are registered.
            adapter_name = _PLATFORM_ADAPTERS[plat]
            try:
                result = router.execute(
                    Capability.SOCIAL_PUBLISH_POST,
                    params,
                    adapter=adapter_name,
                )
            except TypeError:
                # Older routers without the ``adapter`` kwarg.
                result = router.execute(
                    Capability.SOCIAL_PUBLISH_POST, params,
                )
            if getattr(result, "ok", False):
                per_platform[plat] = {
                    "ok": True,
                    "post_id": (
                        (result.data or {}).get("post_id", "")
                    ),
                }
            else:
                all_ok = False
                err = getattr(result, "error", "") or ""
                per_platform[plat] = {
                    "ok": False,
                    "error": str(err)[:200],
                }
        if all_ok:
            self._record_success(post, per_platform)
            return {
                "state": "published",
                "details": per_platform,
            }
        self._record_failure(
            post,
            last_error=json.dumps(per_platform)[:400],
        )
        return {"state": "failed", "details": per_platform}

    def _record_success(
        self,
        post: SocialPost,
        per_platform: dict[str, Any],
    ) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE social_queue SET state='published', "
                "attempts=attempts+1, last_error='', "
                "published_post_ids=? WHERE post_id = ?",
                (
                    json.dumps(per_platform),
                    post.post_id,
                ),
            )
            self._conn.commit()

    def _record_failure(
        self,
        post: SocialPost,
        *,
        last_error: str,
    ) -> None:
        attempts = post.attempts + 1
        new_state = (
            "failed" if attempts >= _MAX_ATTEMPTS else "queued"
        )
        with self._lock:
            self._conn.execute(
                "UPDATE social_queue SET state=?, "
                "attempts=?, last_error=? WHERE post_id = ?",
                (
                    new_state, attempts, last_error,
                    post.post_id,
                ),
            )
            self._conn.commit()


def _row_to_post(row: sqlite3.Row) -> SocialPost:
    try:
        platforms = tuple(
            p for p in json.loads(row["platforms"] or "[]")
            if isinstance(p, str)
        )
    except ValueError:
        platforms = ()
    try:
        hashtags = tuple(
            t for t in json.loads(row["hashtags"] or "[]")
            if isinstance(t, str)
        )
    except ValueError:
        hashtags = ()
    return SocialPost(
        post_id=str(row["post_id"]),
        platforms=platforms,
        text=str(row["text"] or ""),
        image_url=str(row["image_url"] or ""),
        video_url=str(row["video_url"] or ""),
        link_url=str(row["link_url"] or ""),
        hashtags=hashtags,
        publish_at_unix=int(row["publish_at_unix"]),
        trace_id=str(row["trace_id"] or ""),
        state=str(row["state"] or "queued"),
        attempts=int(row["attempts"] or 0),
        last_error=str(row["last_error"] or ""),
        created_at_unix=int(row["created_at_unix"] or 0),
    )
