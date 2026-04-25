"""Vision adapter — parse + mime tests (network stubbed)."""
from __future__ import annotations

import json
import unittest

from core.adapters.image import vision


class TestParseJson(unittest.TestCase):
    def test_valid_payload(self) -> None:
        text = json.dumps({
            "quality": "85", "lighting": 70,
            "background": "clean", "subject_centered": "yes",
            "hero_suitable": True,
            "issues": ["glare", 42, "too dark"],
            "description": "Red magnetic phone mount on white background",
        })
        out = vision._parse_json(text)
        self.assertEqual(out["quality"], 85)
        self.assertEqual(out["lighting"], 70)
        self.assertTrue(out["hero_suitable"])
        self.assertEqual(len(out["issues"]), 3)
        self.assertIn("Red magnetic", out["description"])

    def test_strips_markdown_fence(self) -> None:
        text = "```json\n{\"quality\": 40}\n```"
        out = vision._parse_json(text)
        self.assertEqual(out["quality"], 40)

    def test_invalid_json_returns_empty(self) -> None:
        self.assertEqual(vision._parse_json("not json"), {})
        self.assertEqual(vision._parse_json(""), {})


class TestMimeGuess(unittest.TestCase):
    def test_extension(self) -> None:
        self.assertEqual(vision._guess_mime("x.png", b""), "image/png")
        self.assertEqual(vision._guess_mime("x.JPG?v=2", b""), "image/jpeg")
        self.assertEqual(vision._guess_mime("x.webp", b""), "image/webp")

    def test_magic_bytes_png(self) -> None:
        self.assertEqual(
            vision._guess_mime("x", b"\x89PNG\r\n\x1a\n"),
            "image/png",
        )

    def test_magic_bytes_jpeg(self) -> None:
        self.assertEqual(
            vision._guess_mime("x", b"\xff\xd8\xff\xe0"),
            "image/jpeg",
        )


class TestAnalyzeSafety(unittest.TestCase):
    def test_rejects_bad_url(self) -> None:
        self.assertEqual(vision.analyze(""), {})
        self.assertEqual(vision.analyze("ftp://x.com/a.jpg"), {})

    def test_unconfigured_returns_empty(self) -> None:
        import os
        from unittest.mock import patch
        with patch.dict(os.environ, {"GEMINI_API_KEY": "", "GOOGLE_API_KEY": ""}):
            self.assertEqual(
                vision.analyze("https://example.com/a.jpg"),
                {},
            )


if __name__ == "__main__":
    unittest.main()
