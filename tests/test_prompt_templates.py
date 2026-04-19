"""Prompt templates tests."""
from __future__ import annotations

import unittest

from core.system import prompt_templates as pt


class TestRegister(unittest.TestCase):
    def setUp(self) -> None:
        self.reg = pt.PromptRegistry()

    def test_register_and_get_latest(self) -> None:
        self.reg.register(
            "t", 1, body="Hello {name}",
            required_vars=("name",),
        )
        latest = self.reg.latest("t")
        self.assertIsNotNone(latest)
        self.assertEqual(latest.version, 1)

    def test_multiple_versions_latest_is_highest(self) -> None:
        self.reg.register("t", 1, "v1 {x}", required_vars=("x",))
        self.reg.register("t", 3, "v3 {x}", required_vars=("x",))
        self.reg.register("t", 2, "v2 {x}", required_vars=("x",))
        self.assertEqual(self.reg.latest("t").version, 3)

    def test_blank_name_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.reg.register("", 1, "x", required_vars=())

    def test_blank_body_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.reg.register("t", 1, "", required_vars=())

    def test_declared_var_not_in_body_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.reg.register(
                "t", 1, "Hello {name}",
                required_vars=("name", "extra"),
            )


class TestRender(unittest.TestCase):
    def setUp(self) -> None:
        self.reg = pt.PromptRegistry()
        self.reg.register(
            "greet", 1, body="Hello {name}, about {topic}",
            required_vars=("name", "topic"),
            max_output_tokens=100,
        )

    def test_render_substitutes(self) -> None:
        r = self.reg.render("greet",
                             {"name": "Alice", "topic": "pricing"})
        self.assertEqual(r.rendered, "Hello Alice, about pricing")

    def test_missing_var_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.reg.render("greet", {"name": "Alice"})

    def test_unknown_template_raises(self) -> None:
        with self.assertRaises(KeyError):
            self.reg.render("missing", {})

    def test_render_passes_max_tokens(self) -> None:
        r = self.reg.render("greet",
                             {"name": "A", "topic": "x"})
        self.assertEqual(r.max_output_tokens, 100)


class TestLock(unittest.TestCase):
    def setUp(self) -> None:
        self.reg = pt.PromptRegistry()
        self.reg.register("t", 1, "v1 {x}", required_vars=("x",))
        self.reg.register("t", 2, "v2 {x}", required_vars=("x",))

    def test_lock_pins_version(self) -> None:
        self.assertTrue(self.reg.lock("t", 1))
        r = self.reg.render("t", {"x": "hi"})
        self.assertEqual(r.version, 1)
        self.assertTrue(r.rendered.startswith("v1"))

    def test_unlock_restores_latest(self) -> None:
        self.reg.lock("t", 1)
        self.assertTrue(self.reg.unlock("t"))
        r = self.reg.render("t", {"x": "hi"})
        self.assertEqual(r.version, 2)

    def test_lock_unknown_version_false(self) -> None:
        self.assertFalse(self.reg.lock("t", 99))


class TestHistory(unittest.TestCase):
    def test_history_sorted(self) -> None:
        reg = pt.PromptRegistry()
        reg.register("t", 3, "v3 {x}", required_vars=("x",))
        reg.register("t", 1, "v1 {x}", required_vars=("x",))
        reg.register("t", 2, "v2 {x}", required_vars=("x",))
        h = reg.history("t")
        self.assertEqual([x.version for x in h], [1, 2, 3])


class TestDefaults(unittest.TestCase):
    def test_product_description_registered(self) -> None:
        reg = pt.PromptRegistry()
        t = reg.latest("product_description")
        self.assertIsNotNone(t)
        self.assertIn("{title}", t.body)

    def test_intent_classify_render(self) -> None:
        reg = pt.PromptRegistry()
        r = reg.render("intent_classify",
                        {"text": "I want a refund"})
        self.assertIn("I want a refund", r.rendered)


class TestExplicitVersion(unittest.TestCase):
    def test_render_with_explicit_version(self) -> None:
        reg = pt.PromptRegistry()
        reg.register("t", 1, "v1 {x}", required_vars=("x",))
        reg.register("t", 2, "v2 {x}", required_vars=("x",))
        r = reg.render("t", {"x": "hi"}, version=1)
        self.assertEqual(r.version, 1)


class TestShortcut(unittest.TestCase):
    def test_render_shortcut_uses_singleton(self) -> None:
        r = pt.render("intent_classify", {"text": "hello"})
        self.assertIn("hello", r.rendered)


if __name__ == "__main__":
    unittest.main()
