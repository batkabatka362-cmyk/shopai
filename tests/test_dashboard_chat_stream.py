"""Dashboard chat streaming — Option E.

Exercises the SSE/typewriter pipeline:

* ``_stream_text`` — word-batches the prepared reply, emits a final
  ``{"done": True}`` frame, and survives client disconnect mid-stream.
* ``_send_stream_event`` — JSON-serialises the payload with the
  ``data: ...\\n\\n`` SSE frame envelope and flushes so a slow consumer
  sees deltas promptly.
* ``_handle_chat_stream`` — validates the payload, delegates body
  preparation to ``_process_chat``, and still writes an error-delta
  frame when the pipeline explodes rather than surfacing a 500.
"""
from __future__ import annotations

import io
import json

import pytest

from dashboard.app import DashboardAPIHandler


def _handler() -> DashboardAPIHandler:
    h = object.__new__(DashboardAPIHandler)
    h.wfile = io.BytesIO()
    # _begin_stream writes through send_response/send_header, which
    # require a different plumbing — tests that exercise the full
    # endpoint will stub _begin_stream/_finish_stream out.
    h._captured = []

    def _json(status, data):
        h._captured.append((status, data))

    h._json = _json
    return h


# ---------------------------------------------------------------------------
# _send_stream_event — frame shape
# ---------------------------------------------------------------------------


class TestSendStreamEvent:
    def test_produces_sse_frame(self):
        h = _handler()
        h._send_stream_event({"delta": "hello"})
        raw = h.wfile.getvalue().decode("utf-8")
        assert raw.startswith("data: ")
        assert raw.endswith("\n\n")
        payload = raw[len("data: "):-2]
        assert json.loads(payload) == {"delta": "hello"}

    def test_preserves_unicode(self):
        h = _handler()
        h._send_stream_event({"delta": "сайн байна"})
        raw = h.wfile.getvalue().decode("utf-8")
        assert "сайн байна" in raw  # ensure_ascii=False

    def test_done_event(self):
        h = _handler()
        h._send_stream_event({"done": True})
        raw = h.wfile.getvalue().decode("utf-8")
        assert json.loads(raw[len("data: "):-2]) == {"done": True}


# ---------------------------------------------------------------------------
# _stream_text — batching + completion
# ---------------------------------------------------------------------------


def _parse_frames(raw: str):
    frames = [f.strip() for f in raw.split("\n\n") if f.strip()]
    out = []
    for f in frames:
        assert f.startswith("data: ")
        out.append(json.loads(f[len("data: "):]))
    return out


class TestStreamText:
    def test_empty_string_still_emits_done(self, monkeypatch):
        h = _handler()
        monkeypatch.setattr("time.sleep", lambda *_: None)
        h._stream_text("")
        frames = _parse_frames(h.wfile.getvalue().decode("utf-8"))
        assert frames[-1] == {"done": True}

    def test_deltas_reassemble_to_source(self, monkeypatch):
        h = _handler()
        monkeypatch.setattr("time.sleep", lambda *_: None)
        source = "The quick brown fox jumps over the lazy dog."
        h._stream_text(source)
        frames = _parse_frames(h.wfile.getvalue().decode("utf-8"))
        deltas = [f["delta"] for f in frames if "delta" in f]
        assert "".join(deltas) == source
        assert frames[-1] == {"done": True}

    def test_batches_multiple_words(self, monkeypatch):
        h = _handler()
        monkeypatch.setattr("time.sleep", lambda *_: None)
        # 9 words → 3 batches of 3 + done
        h._stream_text("one two three four five six seven eight nine")
        frames = _parse_frames(h.wfile.getvalue().decode("utf-8"))
        deltas = [f for f in frames if "delta" in f]
        assert len(deltas) == 3

    def test_survives_broken_pipe(self, monkeypatch):
        h = _handler()
        monkeypatch.setattr("time.sleep", lambda *_: None)

        calls = {"n": 0}

        def _send(payload):
            calls["n"] += 1
            if calls["n"] == 2:
                raise BrokenPipeError()

        h._send_stream_event = _send
        # Must not raise even though the client disconnected.
        h._stream_text("alpha beta gamma delta epsilon zeta")

    def test_preserves_unicode_content(self, monkeypatch):
        h = _handler()
        monkeypatch.setattr("time.sleep", lambda *_: None)
        source = "Монгол хэл дээр хариулт өгч байна."
        h._stream_text(source)
        frames = _parse_frames(h.wfile.getvalue().decode("utf-8"))
        deltas = [f["delta"] for f in frames if "delta" in f]
        assert "".join(deltas) == source


# ---------------------------------------------------------------------------
# _handle_chat_stream — validation + wiring
# ---------------------------------------------------------------------------


class TestHandleChatStream:
    def test_rejects_empty_message(self):
        h = _handler()
        h._handle_chat_stream({"message": ""})
        status, data = h._captured[-1]
        assert status == 400
        assert "message" in data["error"].lower()

    def test_rejects_missing_message(self):
        h = _handler()
        h._handle_chat_stream({})
        status, data = h._captured[-1]
        assert status == 400

    def test_invokes_process_chat_with_history(self, monkeypatch):
        h = _handler()
        monkeypatch.setattr("time.sleep", lambda *_: None)
        seen = {}

        def _fake(msg, hist):
            seen["msg"] = msg
            seen["hist"] = hist
            return "hi there friend"

        h._process_chat = _fake
        h._begin_stream = lambda: None
        h._finish_stream = lambda: None

        h._handle_chat_stream({
            "message": "hello",
            "history": [{"role": "user", "content": "prior"}],
        })
        assert seen["msg"] == "hello"
        assert seen["hist"] == [{"role": "user", "content": "prior"}]

    def test_drops_non_list_history(self, monkeypatch):
        h = _handler()
        monkeypatch.setattr("time.sleep", lambda *_: None)
        seen = {}
        h._process_chat = lambda m, hist: seen.setdefault("hist", hist) or "ok"
        h._begin_stream = lambda: None
        h._finish_stream = lambda: None
        h._handle_chat_stream({"message": "hi", "history": "not a list"})
        assert seen["hist"] == []

    def test_process_chat_exception_streams_error_body(self, monkeypatch):
        h = _handler()
        monkeypatch.setattr("time.sleep", lambda *_: None)

        def _boom(*_):
            raise RuntimeError("llm offline")

        h._process_chat = _boom
        h._begin_stream = lambda: None
        h._finish_stream = lambda: None

        h._handle_chat_stream({"message": "hi"})
        raw = h.wfile.getvalue().decode("utf-8")
        frames = _parse_frames(raw)
        joined = "".join(f.get("delta", "") for f in frames)
        assert "llm offline" in joined
        assert frames[-1] == {"done": True}

    def test_calls_begin_and_finish(self, monkeypatch):
        h = _handler()
        monkeypatch.setattr("time.sleep", lambda *_: None)
        flags = {"begin": False, "finish": False}
        h._begin_stream = lambda: flags.__setitem__("begin", True)
        h._finish_stream = lambda: flags.__setitem__("finish", True)
        h._process_chat = lambda m, hist: "reply text"
        h._handle_chat_stream({"message": "hi"})
        assert flags["begin"] is True
        assert flags["finish"] is True
