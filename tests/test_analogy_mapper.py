"""Analogy mapper tests."""
from __future__ import annotations

import unittest

from core.brain import analogy_mapper as am


class TestRegistry(unittest.TestCase):
    def test_register_and_list(self) -> None:
        m = am.AnalogyMapper()
        m.register(am.Template(name="t1", roles=("a",)))
        self.assertEqual(len(m.templates()), 1)

    def test_duplicate_raises(self) -> None:
        m = am.AnalogyMapper()
        m.register(am.Template(name="t", roles=()))
        with self.assertRaises(ValueError):
            m.register(am.Template(name="t", roles=()))

    def test_blank_name_raises(self) -> None:
        m = am.AnalogyMapper()
        with self.assertRaises(ValueError):
            m.register(am.Template(name="", roles=()))

    def test_unregister(self) -> None:
        m = am.AnalogyMapper()
        m.register(am.Template(name="t", roles=()))
        self.assertTrue(m.unregister("t"))
        self.assertFalse(m.unregister("t"))


class TestMapOne(unittest.TestCase):
    def test_identity_mapping_full_score(self) -> None:
        tpl = am.Template(
            name="cheap_impulse",
            roles=("product", "market"),
            relations=[
                ("product", "price_tier", "cheap"),
                ("market", "saturation", "high"),
            ],
        )
        sit = am.Situation(
            roles=("product", "market"),
            relations=[
                ("product", "price_tier", "cheap"),
                ("market", "saturation", "high"),
            ],
        )
        m = am.map_one(tpl, sit)
        self.assertEqual(m.score, 1.0)
        self.assertEqual(m.bindings["product"], "product")

    def test_partial_match(self) -> None:
        tpl = am.Template(
            name="t",
            roles=("p",),
            relations=[
                ("p", "tier", "cheap"),
                ("p", "brand", "premium"),
            ],
        )
        sit = am.Situation(
            roles=("p",),
            relations=[
                ("p", "tier", "cheap"),
            ],
        )
        m = am.map_one(tpl, sit)
        self.assertEqual(m.matched, 1)
        self.assertEqual(m.total, 2)
        self.assertEqual(m.score, 0.5)

    def test_role_renaming(self) -> None:
        # Template uses role "product" — situation calls it "item" but
        # the shape is identical. The mapper should find the binding.
        tpl = am.Template(
            name="t",
            roles=("product",),
            relations=[("product", "tier", "cheap")],
        )
        sit = am.Situation(
            roles=("item",),
            relations=[("item", "tier", "cheap")],
        )
        m = am.map_one(tpl, sit)
        self.assertEqual(m.score, 1.0)
        self.assertEqual(m.bindings["product"], "item")

    def test_zero_match(self) -> None:
        tpl = am.Template(
            name="t", roles=("p",),
            relations=[("p", "tier", "premium")],
        )
        sit = am.Situation(
            roles=("p",),
            relations=[("p", "tier", "cheap")],
        )
        m = am.map_one(tpl, sit)
        self.assertEqual(m.score, 0.0)

    def test_no_roles_template(self) -> None:
        tpl = am.Template(
            name="t", roles=(),
            relations=[("x", "y", "z")],
        )
        sit = am.Situation(
            roles=(),
            relations=[("x", "y", "z")],
        )
        m = am.map_one(tpl, sit)
        self.assertEqual(m.score, 1.0)

    def test_two_role_cross_binding(self) -> None:
        # Template says (product, in_category, audio) (market, saturation, high)
        # Situation names them swapped — mapper should find best binding
        tpl = am.Template(
            name="t",
            roles=("product", "market"),
            relations=[
                ("product", "in_category", "audio"),
                ("market", "saturation", "high"),
            ],
        )
        sit = am.Situation(
            roles=("m1", "p1"),
            relations=[
                ("p1", "in_category", "audio"),
                ("m1", "saturation", "high"),
            ],
        )
        m = am.map_one(tpl, sit)
        self.assertEqual(m.score, 1.0)
        self.assertEqual(m.bindings["product"], "p1")
        self.assertEqual(m.bindings["market"], "m1")


class TestMapperBest(unittest.TestCase):
    def test_best_match_picks_highest_scorer(self) -> None:
        m = am.AnalogyMapper()
        m.register(am.Template(
            name="good",
            roles=("p",),
            relations=[("p", "tier", "cheap")],
        ))
        m.register(am.Template(
            name="bad",
            roles=("p",),
            relations=[("p", "tier", "premium")],
        ))
        sit = am.Situation(
            roles=("p",),
            relations=[("p", "tier", "cheap")],
        )
        best = m.best_match(sit)
        self.assertEqual(best.template.name, "good")

    def test_below_min_score_returns_none(self) -> None:
        m = am.AnalogyMapper()
        m.register(am.Template(
            name="t",
            roles=("p",),
            relations=[
                ("p", "a", 1), ("p", "b", 2), ("p", "c", 3),
                ("p", "d", 4),
            ],
        ))
        sit = am.Situation(
            roles=("p",),
            relations=[("p", "a", 1)],
        )
        best = m.best_match(sit, min_score=0.5)
        self.assertIsNone(best)

    def test_empty_registry_returns_none(self) -> None:
        m = am.AnalogyMapper()
        sit = am.Situation(roles=("p",), relations=[])
        self.assertIsNone(m.best_match(sit))

    def test_match_all_sorted(self) -> None:
        m = am.AnalogyMapper()
        for i in range(3):
            m.register(am.Template(
                name=f"t{i}",
                roles=("p",),
                relations=[("p", "n", i)],
            ))
        sit = am.Situation(
            roles=("p",),
            relations=[("p", "n", 1)],
        )
        matches = m.match_all(sit)
        self.assertEqual(matches[0].template.name, "t1")


class TestDict(unittest.TestCase):
    def test_template_as_dict(self) -> None:
        tpl = am.Template(name="t", roles=("p",), relations=[("p", "a", 1)])
        d = tpl.as_dict()
        self.assertEqual(d["name"], "t")
        self.assertEqual(d["roles"], ["p"])

    def test_match_as_dict(self) -> None:
        m = am.Match(
            template=am.Template(name="t", roles=()),
            score=0.75, bindings={"a": "b"},
            matched=3, total=4,
        )
        d = m.as_dict()
        self.assertEqual(d["template"], "t")
        self.assertEqual(d["score"], 0.75)


if __name__ == "__main__":
    unittest.main()
