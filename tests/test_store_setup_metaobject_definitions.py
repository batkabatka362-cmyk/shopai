"""Tests for ``engines.store_setup.metaobject_definitions``.

Generator produces niche-aware metaobject definition specs;
applier pushes each via
``SHOPIFY_CREATE_METAOBJECT_DEFINITION`` and records via
Pattern Z.

Coverage:
  1. Generator: empty store_name -> empty dict.
  2. Generator: every niche has at least 1 definition.
  3. Generator: each definition has type + name +
     description + field_definitions list (non-empty).
  4. Generator: each field has key + type (the two
     adapter-required fields).
  5. Generator: at least one required field per definition.
  6. Generator: every niche resolves (no KeyError).
  7. Generator: unknown niche falls back to general
     (TeamMember).
  8. Generator: niche-specific definitions surface
     (Ingredient for beauty, Material for fashion, Recipe
     for food, Stone for jewelry, Stage for baby, ...).
  9. Generator: types are slug-cased lowercase.
 10. Generator: deep-copy semantics -- caller mutation
     doesn't poison the library.
 11. Applier: empty / non-dict short-circuit.
 12. Applier: router_unavailable + per-definition recording.
 13. Applier: missing type skipped.
 14. Applier: success + Pattern Z per definition.
 15. Applier: per-definition failure isolation.
 16. Applier: adapter raise isolation.
 17. Applier: definition_id captured on success.
 18. store_id propagation.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from engines.store_setup.metaobject_definitions import (
    _NICHE_DEFINITIONS,
    apply_metaobject_pack,
    generate_metaobject_pack,
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
        assert generate_metaobject_pack(store_name="") == {}
        assert (
            generate_metaobject_pack(store_name="   ") == {}
        )
        assert (
            generate_metaobject_pack(store_name=None) == {}
        )


class TestGeneratorShape:

    def test_at_least_one_definition_per_niche(self):
        for niche in _NICHE_DEFINITIONS:
            spec = generate_metaobject_pack(
                store_name="Acme", niche=niche,
            )
            assert len(spec["definitions"]) >= 1, niche

    def test_every_definition_has_full_shape(self):
        for niche in _NICHE_DEFINITIONS:
            spec = generate_metaobject_pack(
                store_name="Acme", niche=niche,
            )
            for d in spec["definitions"]:
                assert d["type"], niche
                assert d["name"], niche
                assert d["description"], niche
                assert isinstance(
                    d["field_definitions"], list,
                )
                assert len(d["field_definitions"]) >= 2, (
                    niche, d["type"],
                )

    def test_each_field_has_key_and_type(self):
        for niche in _NICHE_DEFINITIONS:
            spec = generate_metaobject_pack(
                store_name="Acme", niche=niche,
            )
            for d in spec["definitions"]:
                for f in d["field_definitions"]:
                    assert f["key"], (niche, d["type"])
                    assert f["type"], (niche, d["type"])

    def test_at_least_one_required_field_per_definition(self):
        """Without a required field the operator can save
        an empty metaobject -- usually meaningless."""
        for niche in _NICHE_DEFINITIONS:
            spec = generate_metaobject_pack(
                store_name="Acme", niche=niche,
            )
            for d in spec["definitions"]:
                requireds = [
                    f for f in d["field_definitions"]
                    if f.get("required")
                ]
                assert len(requireds) >= 1, (
                    niche, d["type"],
                )

    def test_every_niche_resolves(self):
        for niche in (
            "beauty", "fashion", "tech", "home", "food",
            "pets", "fitness", "jewelry", "outdoor",
            "baby", "general", "ufo_parts",
        ):
            spec = generate_metaobject_pack(
                store_name="Acme", niche=niche,
            )
            assert spec["definitions"]

    def test_unknown_niche_falls_back_to_general(self):
        spec = generate_metaobject_pack(
            store_name="Acme", niche="ufo_parts",
        )
        assert (
            len(spec["definitions"])
            == len(_NICHE_DEFINITIONS["general"])
        )
        # TeamMember is the general definition
        assert spec["definitions"][0]["type"] == (
            "team_member"
        )


class TestNicheSpecificity:

    def test_niche_specific_types_surface(self):
        """Each niche surfaces its hallmark type."""
        cases = {
            "beauty": "ingredient",
            "fashion": "material",
            "tech": "specification",
            "food": "recipe",
            "jewelry": "stone",
            "baby": "stage",
            "outdoor": "temp_rating",
            "fitness": "exercise",
        }
        for niche, expected_type in cases.items():
            spec = generate_metaobject_pack(
                store_name="Acme", niche=niche,
            )
            types = {
                d["type"] for d in spec["definitions"]
            }
            assert expected_type in types, niche

    def test_types_slug_cased(self):
        """All type handles are lowercase + underscored
        (Shopify storefront handle convention)."""
        for niche in _NICHE_DEFINITIONS:
            spec = generate_metaobject_pack(
                store_name="Acme", niche=niche,
            )
            for d in spec["definitions"]:
                t = d["type"]
                assert t == t.lower(), (niche, t)
                assert " " not in t, (niche, t)


class TestDeepCopySemantics:

    def test_caller_mutation_doesnt_poison_library(self):
        spec = generate_metaobject_pack(
            store_name="Acme", niche="beauty",
        )
        spec["definitions"][0]["field_definitions"].append(
            {"key": "ufo", "type": "single_line_text_field"},
        )
        # Fetch again - should not see the mutation
        spec2 = generate_metaobject_pack(
            store_name="Acme", niche="beauty",
        )
        keys = [
            f["key"]
            for f in spec2["definitions"][0][
                "field_definitions"
            ]
        ]
        assert "ufo" not in keys


# ── Applier ──────────────────────────────────────────────────


class TestApplierEmpty:

    def test_non_dict(self):
        out = apply_metaobject_pack(None)  # type: ignore[arg-type]
        assert out["applied_count"] == 0

    def test_empty_spec(self):
        out = apply_metaobject_pack({})
        assert out["applied_count"] == 0

    def test_spec_without_definitions(self):
        out = apply_metaobject_pack(
            {"store_name": "Acme"},
        )
        assert out["applied_count"] == 0


class TestApplierRouterFailure:

    def test_router_unavailable_records_each(self):
        spec = generate_metaobject_pack(
            store_name="Acme", niche="beauty",
        )
        with patch(
            "engines.store_setup.metaobject_definitions."
            "_get_router",
            return_value=None,
        ), patch(
            "engines.store_setup.metaobject_definitions."
            "record_writeback",
        ) as record_mock:
            out = apply_metaobject_pack(spec)
        assert out["applied_count"] == 0
        assert (
            record_mock.call_count
            == len(spec["definitions"])
        )


class TestApplierSuccess:

    def test_all_definitions_applied(self):
        router = MagicMock()
        ids = iter([f"gid://d/{i}" for i in range(20)])

        def _exec(cap, params):
            return _ok(
                {"definition": {"id": next(ids)}},
            )

        router.execute.side_effect = _exec
        spec = generate_metaobject_pack(
            store_name="Acme", niche="beauty",
        )
        with patch(
            "engines.store_setup.metaobject_definitions."
            "_get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.metaobject_definitions."
            "record_writeback",
        ) as record_mock:
            out = apply_metaobject_pack(spec)
        assert (
            out["applied_count"] == len(spec["definitions"])
        )
        for r in out["results"]:
            assert r["ok"] is True
            assert r["definition_id"]
        assert (
            record_mock.call_count
            == len(spec["definitions"])
        )

    def test_params_forwarded(self):
        """Full definition dict (type + name + description
        + field_definitions) is forwarded to the adapter."""
        router = MagicMock()
        captured: list[dict] = []

        def _exec(cap, params):
            captured.append(params)
            return _ok({"definition": {"id": "gid://d/1"}})

        router.execute.side_effect = _exec
        spec = generate_metaobject_pack(
            store_name="Acme", niche="beauty",
        )
        with patch(
            "engines.store_setup.metaobject_definitions."
            "_get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.metaobject_definitions."
            "record_writeback",
        ):
            apply_metaobject_pack(spec)
        assert len(captured) == len(spec["definitions"])
        for p, d in zip(captured, spec["definitions"]):
            assert p["type"] == d["type"]
            assert p["name"] == d["name"]
            assert (
                p["field_definitions"]
                == d["field_definitions"]
            )

    def test_alternative_response_key(self):
        """Adapter may surface the new node as
        `metaobject_definition` (legacy) instead of
        `definition` -- applier handles both."""
        router = MagicMock()
        router.execute.return_value = _ok({
            "metaobject_definition": {
                "id": "gid://d/legacy",
            },
        })
        spec = generate_metaobject_pack(
            store_name="Acme", niche="general",
        )
        with patch(
            "engines.store_setup.metaobject_definitions."
            "_get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.metaobject_definitions."
            "record_writeback",
        ):
            out = apply_metaobject_pack(spec)
        # 1 definition for general, both response shapes
        # captured
        assert out["applied_count"] == 1
        assert (
            out["results"][0]["definition_id"]
            == "gid://d/legacy"
        )


class TestApplierFailureIsolation:

    def test_missing_type_skipped(self):
        router = MagicMock()
        router.execute.return_value = _ok(
            {"definition": {"id": "gid://d/1"}},
        )
        spec = {
            "store_name": "Acme",
            "niche": "general",
            "definitions": [
                {
                    "type": "",
                    "name": "Bad",
                    "field_definitions": [],
                },
                {
                    "type": "good",
                    "name": "Good",
                    "field_definitions": [
                        {"key": "k", "type": "x"},
                    ],
                },
            ],
        }
        with patch(
            "engines.store_setup.metaobject_definitions."
            "_get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.metaobject_definitions."
            "record_writeback",
        ):
            out = apply_metaobject_pack(spec)
        # Bad skipped, Good applied
        assert out["applied_count"] == 1
        assert out["results"][0]["error"] == "missing_type"

    def test_partial_failure(self):
        router = MagicMock()

        def _exec(cap, params):
            if params["type"] == "ingredient":
                return _fail("type taken")
            return _ok({"definition": {"id": "gid://d/1"}})

        router.execute.side_effect = _exec
        spec = generate_metaobject_pack(
            store_name="Acme", niche="beauty",
        )
        with patch(
            "engines.store_setup.metaobject_definitions."
            "_get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.metaobject_definitions."
            "record_writeback",
        ):
            out = apply_metaobject_pack(spec)
        # Only ingredient exists in beauty (1 def); failure
        # -> 0 applied
        assert out["applied_count"] == 0
        assert (
            "type taken" in out["results"][0]["error"]
        )

    def test_adapter_raise_isolates(self):
        """If a definition raises, the others still try."""
        router = MagicMock()
        call_count = {"i": 0}

        def _exec(cap, params):
            call_count["i"] += 1
            if call_count["i"] == 1:
                raise RuntimeError("network")
            return _ok({"definition": {"id": "gid://d/1"}})

        # Use 2-definition niche: not available, so build
        # a manual spec.
        router.execute.side_effect = _exec
        spec = {
            "store_name": "Acme",
            "niche": "general",
            "definitions": [
                {
                    "type": "first",
                    "name": "First",
                    "field_definitions": [
                        {"key": "k", "type": "x"},
                    ],
                },
                {
                    "type": "second",
                    "name": "Second",
                    "field_definitions": [
                        {"key": "k", "type": "x"},
                    ],
                },
            ],
        }
        with patch(
            "engines.store_setup.metaobject_definitions."
            "_get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.metaobject_definitions."
            "record_writeback",
        ):
            out = apply_metaobject_pack(spec)
        assert out["applied_count"] == 1
        # First raised, second succeeded
        assert "network" in out["results"][0]["error"]
        assert out["results"][1]["ok"] is True


# ── store_id propagation ─────────────────────────────────────


class TestStoreIdPropagation:

    def test_store_id_recorded_per_definition(self):
        router = MagicMock()
        router.execute.return_value = _ok(
            {"definition": {"id": "gid://d/1"}},
        )
        spec = generate_metaobject_pack(
            store_name="Acme", niche="general",
        )
        with patch(
            "engines.store_setup.metaobject_definitions."
            "_get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.metaobject_definitions."
            "record_writeback",
        ) as record_mock:
            apply_metaobject_pack(
                spec, store_id="store-a",
            )
        for call in record_mock.call_args_list:
            assert (
                call.kwargs["params"]["store_id"]
                == "store-a"
            )
