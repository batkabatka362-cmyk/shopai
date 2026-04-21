"""Autopilot loop llms.txt auto-rebuild tests (E-1 follow-on)."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts import autopilot_loop as al


def _make_config(
    log_path: str,
    seeds_path: str,
    **overrides,
):
    defaults = dict(
        log_path=log_path,
        seeds_path=seeds_path,
        interval_s=1.0,
        max_iterations=1,
        llms_txt_rebuild_every=1,
        distill_every=99,  # disable distill during tests
    )
    defaults.update(overrides)
    return al.LoopConfig(**defaults)


def _write_seeds(path: str):
    Path(path).write_text(json.dumps([{
        "title": "Pet Bowl",
        "price": 29.99,
        "cost": 8.0,
        "daily_sales": 10,
        "saturation_score": 0.3,
        "image_url": "https://cdn/pet.jpg",
        "url": "https://aliexpress/x",
        "source": "manual",
        "external_id": "ali-1",
    }]))


def _fake_products() -> list[dict]:
    return [
        {
            "handle": "pet-bowl",
            "title": "Pet Bowl",
            "description": "Slow-feed.",
            "price": 29.99,
        },
        {
            "handle": "cat-tree",
            "title": "Cat Tree",
            "description": "Multi-level.",
            "price": 89.99,
        },
    ]


class TestLlmsTxtRebuild(unittest.TestCase):
    def setUp(self):
        self._orig = os.environ.get(
            "SHOPAI_SHOPIFY_URL",
        )
        os.environ["SHOPAI_SHOPIFY_URL"] = (
            "example.myshopify.com"
        )

    def tearDown(self):
        if self._orig is None:
            os.environ.pop("SHOPAI_SHOPIFY_URL", None)
        else:
            os.environ["SHOPAI_SHOPIFY_URL"] = self._orig

    def test_rebuilds_on_cycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            seeds = str(Path(tmp) / "seeds.json")
            _write_seeds(seeds)
            cfg = _make_config(
                log_path=str(Path(tmp) / "log.jsonl"),
                seeds_path=seeds,
                llms_txt_rebuild_every=1,
                llms_txt_out_dir=str(
                    Path(tmp) / "llms",
                ),
            )
            fake_conn = MagicMock()
            fake_conn.fetch_store_data.return_value = {
                "products": _fake_products(),
            }
            loop = al.AutopilotLoop(
                cfg,
                autopilot=MagicMock(
                    run=MagicMock(return_value=MagicMock(
                        launches=[], successful_launches=0,
                    )),
                ),
                launch_learner=MagicMock(),
            )
            with patch(
                "core.bridge.shopify_connector"
                ".ShopifyLiveConnector",
                return_value=fake_conn,
            ):
                summary = loop._run_one_cycle()
            self.assertFalse(summary.error)
            out = Path(cfg.llms_txt_out_dir)
            self.assertTrue(
                (out / "llms.txt").exists(),
            )
            self.assertTrue(
                (out / "llms-full.txt").exists(),
            )
            self.assertTrue(
                (out / "products" / "pet-bowl.md").exists(),
            )

    def test_rebuild_every_zero_disables(self):
        with tempfile.TemporaryDirectory() as tmp:
            seeds = str(Path(tmp) / "seeds.json")
            _write_seeds(seeds)
            cfg = _make_config(
                log_path=str(Path(tmp) / "log.jsonl"),
                seeds_path=seeds,
                llms_txt_rebuild_every=0,
                llms_txt_out_dir=str(
                    Path(tmp) / "llms",
                ),
            )
            loop = al.AutopilotLoop(
                cfg,
                autopilot=MagicMock(
                    run=MagicMock(return_value=MagicMock(
                        launches=[], successful_launches=0,
                    )),
                ),
                launch_learner=MagicMock(),
            )
            with patch(
                "core.bridge.shopify_connector"
                ".ShopifyLiveConnector",
            ) as _sl:
                loop._run_one_cycle()
            self.assertFalse(_sl.called)
            out = Path(cfg.llms_txt_out_dir)
            self.assertFalse((out / "llms.txt").exists())

    def test_fetch_failure_soft(self):
        with tempfile.TemporaryDirectory() as tmp:
            seeds = str(Path(tmp) / "seeds.json")
            _write_seeds(seeds)
            cfg = _make_config(
                log_path=str(Path(tmp) / "log.jsonl"),
                seeds_path=seeds,
                llms_txt_rebuild_every=1,
                llms_txt_out_dir=str(
                    Path(tmp) / "llms",
                ),
            )
            fake_conn = MagicMock()
            fake_conn.fetch_store_data.side_effect = (
                RuntimeError("shopify down")
            )
            loop = al.AutopilotLoop(
                cfg,
                autopilot=MagicMock(
                    run=MagicMock(return_value=MagicMock(
                        launches=[], successful_launches=0,
                    )),
                ),
                launch_learner=MagicMock(),
            )
            with patch(
                "core.bridge.shopify_connector"
                ".ShopifyLiveConnector",
                return_value=fake_conn,
            ):
                summary = loop._run_one_cycle()
            # Cycle must finish — rebuild raise ≠ cycle abort
            self.assertIsNotNone(summary)
            # No llms.txt produced (fetch failed)
            out = Path(cfg.llms_txt_out_dir)
            self.assertFalse((out / "llms.txt").exists())

    def test_no_shopify_url_skips(self):
        os.environ.pop("SHOPAI_SHOPIFY_URL", None)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                seeds = str(Path(tmp) / "seeds.json")
                _write_seeds(seeds)
                cfg = _make_config(
                    log_path=str(Path(tmp) / "log.jsonl"),
                    seeds_path=seeds,
                    llms_txt_rebuild_every=1,
                    llms_txt_out_dir=str(
                        Path(tmp) / "llms",
                    ),
                )
                loop = al.AutopilotLoop(
                    cfg,
                    autopilot=MagicMock(
                        run=MagicMock(
                            return_value=MagicMock(
                                launches=[],
                                successful_launches=0,
                            ),
                        ),
                    ),
                    launch_learner=MagicMock(),
                )
                with patch(
                    "core.bridge.shopify_connector"
                    ".ShopifyLiveConnector",
                ) as _sl:
                    loop._run_one_cycle()
                self.assertFalse(_sl.called)
        finally:
            os.environ["SHOPAI_SHOPIFY_URL"] = (
                "example.myshopify.com"
            )

    def test_empty_products_no_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            seeds = str(Path(tmp) / "seeds.json")
            _write_seeds(seeds)
            cfg = _make_config(
                log_path=str(Path(tmp) / "log.jsonl"),
                seeds_path=seeds,
                llms_txt_rebuild_every=1,
                llms_txt_out_dir=str(
                    Path(tmp) / "llms",
                ),
            )
            fake_conn = MagicMock()
            fake_conn.fetch_store_data.return_value = {
                "products": [],
            }
            loop = al.AutopilotLoop(
                cfg,
                autopilot=MagicMock(
                    run=MagicMock(return_value=MagicMock(
                        launches=[], successful_launches=0,
                    )),
                ),
                launch_learner=MagicMock(),
            )
            with patch(
                "core.bridge.shopify_connector"
                ".ShopifyLiveConnector",
                return_value=fake_conn,
            ):
                loop._run_one_cycle()
            out = Path(cfg.llms_txt_out_dir)
            self.assertFalse((out / "llms.txt").exists())


if __name__ == "__main__":
    unittest.main()
