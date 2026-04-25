"""CLI tests for publisher / activator commands.

Validate the argparse wiring + handler dispatch. Uses
``cli.build_parser()`` directly to avoid invoking ``main()``;
handler side-effects are exercised through the real modules in
dry-run mode so no network calls happen.
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import cli


class TestParser(unittest.TestCase):
    """All 4 new subcommands must parse without conflict."""

    def test_publish_parses(self):
        parser = cli.build_parser()
        args = parser.parse_args([
            "publish", "winner.json",
            "--budget", "15",
            "--platform", "tiktok",
        ])
        self.assertEqual(args.command, "publish")
        self.assertEqual(args.winner_json, "winner.json")
        self.assertEqual(args.budget, 15.0)
        self.assertEqual(args.platform, "tiktok")

    def test_activate_parses(self):
        parser = cli.build_parser()
        args = parser.parse_args([
            "activate", "camp_1",
            "--budget", "20",
            "--auto-approve",
        ])
        self.assertEqual(args.command, "activate")
        self.assertEqual(args.campaign_id, "camp_1")
        self.assertTrue(args.auto_approve)

    def test_publications_parses(self):
        parser = cli.build_parser()
        args = parser.parse_args([
            "publications", "--limit", "3",
        ])
        self.assertEqual(args.command, "publications")
        self.assertEqual(args.limit, 3)

    def test_activations_parses(self):
        parser = cli.build_parser()
        args = parser.parse_args([
            "activations", "--limit", "7", "--json",
        ])
        self.assertEqual(args.command, "activations")
        self.assertEqual(args.limit, 7)
        self.assertTrue(args.json)


class TestReadWinner(unittest.TestCase):
    def test_from_file(self):
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False,
        )
        try:
            json.dump({"title": "X", "price": 10}, tmp)
            tmp.close()
            result = cli._read_winner(tmp.name)
            self.assertEqual(result["title"], "X")
        finally:
            os.unlink(tmp.name)

    def test_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            cli._read_winner("/does/not/exist.json")

    def test_non_object_raises(self):
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False,
        )
        try:
            tmp.write('"just a string"')
            tmp.close()
            with self.assertRaises(ValueError):
                cli._read_winner(tmp.name)
        finally:
            os.unlink(tmp.name)

    def test_invalid_json_raises(self):
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False,
        )
        try:
            tmp.write("{this is not json")
            tmp.close()
            with self.assertRaises(ValueError):
                cli._read_winner(tmp.name)
        finally:
            os.unlink(tmp.name)

    def test_from_stdin(self):
        payload = '{"title": "stdin product"}'
        old_stdin = sys.stdin
        sys.stdin = io.StringIO(payload)
        try:
            result = cli._read_winner("-")
            self.assertEqual(
                result["title"], "stdin product",
            )
        finally:
            sys.stdin = old_stdin


class TestPublishHandler(unittest.TestCase):
    """``_cmd_publish`` in dry-run mode (default when
    SHOPAI_ENABLE_LIVE_EXECUTION not set)."""

    def setUp(self):
        self._orig = os.environ.pop(
            "SHOPAI_ENABLE_LIVE_EXECUTION", None,
        )
        self.tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False,
        )
        json.dump(
            {
                "title": "Test Winner",
                "price": 29.99,
                "image_url": "https://x/p.jpg",
            },
            self.tmp,
        )
        self.tmp.close()

    def tearDown(self):
        os.unlink(self.tmp.name)
        if self._orig is not None:
            os.environ[
                "SHOPAI_ENABLE_LIVE_EXECUTION"
            ] = self._orig
        # Scrub any shopify creds we might have injected
        os.environ.setdefault(
            "SHOPAI_SHOPIFY_URL", "x.myshopify.com",
        )

    def test_publish_prints_summary(self):
        os.environ["SHOPAI_SHOPIFY_URL"] = (
            "test.myshopify.com"
        )
        os.environ["SHOPAI_SHOPIFY_KEY"] = "tok"
        buf = io.StringIO()
        with redirect_stdout(buf):
            cli._cmd_publish(
                winner_json=self.tmp.name,
                budget=20.0,
                platform="facebook",
                live=False,
                as_json=False,
            )
        out = buf.getvalue()
        self.assertIn("publish", out)
        self.assertIn("DRY-RUN", out)
        self.assertIn("decision=", out)
        self.assertIn("tracking_url", out)

    def test_publish_json_output(self):
        os.environ["SHOPAI_SHOPIFY_URL"] = (
            "test.myshopify.com"
        )
        os.environ["SHOPAI_SHOPIFY_KEY"] = "tok"
        buf = io.StringIO()
        with redirect_stdout(buf):
            cli._cmd_publish(
                winner_json=self.tmp.name,
                budget=20.0,
                platform="facebook",
                live=False,
                as_json=True,
            )
        data = json.loads(buf.getvalue())
        self.assertIn("decision_id", data)
        self.assertIn("steps", data)

    def test_publish_bad_winner_exits(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            with self.assertRaises(SystemExit) as cm:
                cli._cmd_publish(
                    winner_json="/nope/missing.json",
                    budget=20.0,
                    platform="facebook",
                    live=False,
                    as_json=False,
                )
        self.assertEqual(cm.exception.code, 2)


class TestActivateHandler(unittest.TestCase):
    def setUp(self):
        self._orig = os.environ.pop(
            "SHOPAI_ENABLE_LIVE_EXECUTION", None,
        )

    def tearDown(self):
        if self._orig is not None:
            os.environ[
                "SHOPAI_ENABLE_LIVE_EXECUTION"
            ] = self._orig

    def test_activate_dry_run(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            cli._cmd_activate(
                campaign_id="test_camp",
                budget=20.0,
                auto_approve=True,
                live=False,
                as_json=False,
            )
        out = buf.getvalue()
        self.assertIn("DRY_RUN", out)
        self.assertIn("test_camp", out)

    def test_activate_blank_id_exits(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            with self.assertRaises(SystemExit) as cm:
                cli._cmd_activate(
                    campaign_id="",
                    budget=0.0,
                    auto_approve=True,
                    live=False,
                    as_json=False,
                )
        self.assertEqual(cm.exception.code, 2)


class TestHistoryCommands(unittest.TestCase):
    def test_publications_empty(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            cli._cmd_publications(limit=5, as_json=False)
        out = buf.getvalue()
        self.assertIn("No publications", out)

    def test_activations_empty(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            cli._cmd_activations(limit=5, as_json=False)
        out = buf.getvalue()
        self.assertIn("No activations", out)

    def test_publications_json_empty(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            cli._cmd_publications(limit=5, as_json=True)
        data = json.loads(buf.getvalue())
        self.assertEqual(data, [])


if __name__ == "__main__":
    unittest.main()
