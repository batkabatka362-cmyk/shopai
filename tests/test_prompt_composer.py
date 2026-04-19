"""Prompt composer tests."""
from __future__ import annotations

import unittest

from core.brain import prompt_composer as pc


class TestProvider(unittest.TestCase):
    def test_blank_name_raises(self) -> None:
        with self.assertRaises(ValueError):
            pc.SlotProvider(name="", fn=lambda: "x", slot="s")

    def test_blank_slot_raises(self) -> None:
        with self.assertRaises(ValueError):
            pc.SlotProvider(name="n", fn=lambda: "x", slot="")


class TestIdentityProvider(unittest.TestCase):
    def test_default_identity(self) -> None:
        p = pc.identity_provider()
        self.assertEqual(p.fn(), "ShopAI commerce executor")

    def test_injected_narrator(self) -> None:
        p = pc.identity_provider(
            narrator_fn=lambda: {"identity_line": "custom"},
        )
        self.assertEqual(p.fn(), "custom")

    def test_raising_narrator_falls_back(self) -> None:
        def boom():
            raise RuntimeError("x")

        p = pc.identity_provider(narrator_fn=boom)
        self.assertEqual(p.fn(), "ShopAI commerce executor")


class TestContextProvider(unittest.TestCase):
    def test_empty_context(self) -> None:
        p = pc.context_provider(compactor_fn=lambda: {"fields": {}})
        self.assertEqual(p.fn(), "(no context)")

    def test_fields_rendered_sorted(self) -> None:
        p = pc.context_provider(
            compactor_fn=lambda: {"fields": {"b": 2, "a": 1}},
        )
        body = p.fn()
        self.assertLess(body.index("a: 1"), body.index("b: 2"))


class TestExamplesProvider(unittest.TestCase):
    def test_empty_examples(self) -> None:
        p = pc.examples_provider(examples_fn=lambda: [])
        self.assertEqual(p.fn(), "")

    def test_cap_respects_max(self) -> None:
        examples = [
            {"question": f"q{i}", "answer": f"a{i}"}
            for i in range(10)
        ]
        p = pc.examples_provider(
            examples_fn=lambda: examples, max_examples=2,
        )
        body = p.fn()
        self.assertIn("q0", body)
        self.assertNotIn("q5", body)

    def test_raising_fn_empty(self) -> None:
        def boom():
            raise RuntimeError("x")

        p = pc.examples_provider(examples_fn=boom)
        self.assertEqual(p.fn(), "")


class TestOwnerStyleProvider(unittest.TestCase):
    def test_empty_weights(self) -> None:
        p = pc.owner_style_provider(weights_fn=lambda: {})
        self.assertEqual(p.fn(), "normal")

    def test_dominant_weight(self) -> None:
        p = pc.owner_style_provider(
            weights_fn=lambda: {
                "roas": 0.6, "refund_rate": 0.1,
                "cost": 0.2, "stability": 0.1,
            },
        )
        self.assertEqual(p.fn(), "roas")


class TestComposer(unittest.TestCase):
    def setUp(self) -> None:
        self.templates = {
            "intro": "You are {identity}. Style: {owner_style}.",
            "body":  "Context:\n{context}\n---\n{examples}",
            "q":     "Question: {question}",
        }

        def render(name, vars):
            body = self.templates[name]
            return body.format_map(_DefaultDict(vars))

        self.composer = pc.PromptComposer(
            template_render=render,
            template_version_lookup=lambda n: 1,
        )

    def test_blank_base_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.composer.compose(base_template="")

    def test_override_wins(self) -> None:
        self.composer.register(pc.identity_provider())
        result = self.composer.compose(
            base_template="intro",
            slot_overrides={"identity": "Manual Override"},
        )
        self.assertIn("Manual Override", result.body)
        self.assertEqual(result.slot_sources["identity"], "override")

    def test_provider_fills_missing_slot(self) -> None:
        self.composer.register(pc.identity_provider(
            narrator_fn=lambda: {"identity_line": "hero"},
        ))
        self.composer.register(pc.owner_style_provider(
            weights_fn=lambda: {"roas": 0.9},
        ))
        result = self.composer.compose(base_template="intro")
        self.assertIn("hero", result.body)
        self.assertIn("roas", result.body)
        self.assertEqual(
            result.slot_sources["identity"], "self_narrative",
        )

    def test_missing_required_flagged(self) -> None:
        result = self.composer.compose(
            base_template="q",
            required_slots=("question",),
        )
        self.assertIn("question", result.missing_slots)

    def test_overlay_templates_appended(self) -> None:
        self.composer.register(pc.context_provider(
            compactor_fn=lambda: {"fields": {"cycle_id": "c1"}},
        ))
        self.composer.register(pc.examples_provider(
            examples_fn=lambda: [
                {"question": "Q", "answer": "A"},
            ],
        ))
        self.composer.register(pc.identity_provider())
        self.composer.register(pc.owner_style_provider())
        result = self.composer.compose(
            base_template="intro",
            overlay_templates=["body"],
        )
        self.assertIn("Example 1", result.body)
        self.assertEqual(len(result.templates_used), 2)

    def test_render_failure_shows_placeholder(self) -> None:
        def bad(n, v):
            raise RuntimeError("template broken")

        comp = pc.PromptComposer(template_render=bad)
        result = comp.compose(base_template="anything")
        self.assertIn("unavailable", result.body)

    def test_provider_failure_silently_skipped(self) -> None:
        def boom():
            raise RuntimeError("x")

        self.composer.register(pc.SlotProvider(
            name="boom_provider", fn=boom, slot="custom",
        ))
        self.composer.register(pc.identity_provider())
        self.composer.register(pc.owner_style_provider())
        # Still composes; the broken slot just isn't filled
        result = self.composer.compose(base_template="intro")
        self.assertNotIn("custom", result.slot_sources)

    def test_no_renderer_uses_template_name_literal(self) -> None:
        comp = pc.PromptComposer()
        result = comp.compose(base_template="some-template-name")
        self.assertIn("some-template-name", result.body)


class TestRegistry(unittest.TestCase):
    def test_unregister(self) -> None:
        comp = pc.PromptComposer()
        comp.register(pc.identity_provider())
        self.assertTrue(comp.unregister("identity"))
        self.assertFalse(comp.unregister("identity"))

    def test_overwrite_via_register(self) -> None:
        comp = pc.PromptComposer()
        comp.register(pc.identity_provider())
        replacement = pc.SlotProvider(
            name="other", fn=lambda: "X", slot="identity",
        )
        comp.register(replacement)
        self.assertEqual(comp.stats()["providers"], 1)


class TestStatsDict(unittest.TestCase):
    def test_stats(self) -> None:
        comp = pc.PromptComposer()
        comp.register(pc.identity_provider())
        s = comp.stats()
        self.assertEqual(s["providers"], 1)
        self.assertIn("identity", s["slots"])

    def test_composed_serialises(self) -> None:
        comp = pc.PromptComposer()
        comp.register(pc.identity_provider())
        result = comp.compose(base_template="static body")
        d = result.as_dict()
        self.assertIn("body", d)
        self.assertIn("slot_sources", d)


class _DefaultDict(dict):
    """dict that returns empty string for missing keys during
    .format_map so tests don't explode on partial slots."""

    def __missing__(self, key):
        return ""


if __name__ == "__main__":
    unittest.main()
